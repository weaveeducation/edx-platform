/* global gettext */
/* eslint react/no-array-index-key: 0 */

import PropTypes from 'prop-types';
import React from 'react';
import ReactDOM from 'react-dom';

class CourseOrLibraryListing extends React.Component {
    constructor(props) {
        super(props);
        this.state = {
            orgs: [],
        };
    }

    componentDidMount() {
        this.orgChangeHandler = this.orgChangeHandler.bind(this);
        const orgSelector = document.getElementById('orgs-input');
        if (orgSelector) {
            $(document).on('orgs_changed', this.orgChangeHandler);
        }
    }

    componentWillUnmount() {
        const orgSelector = document.getElementById('orgs-input');
        if (orgSelector) {
            $(document).off('orgs_changed');
        }
    }

    orgChangeHandler(e) {
        const orgs = [];
        if (arguments.length > 0) {
            for (let i = 1; i < arguments.length; i++) {
                orgs.push(arguments[i]);
            }
        }
        this.setState({
            orgs,
        });
    }

    render() {
        const { allowReruns } = props;
        const { linkClass } = props;
        const { idBase } = props;

        const renderCourseMetadata = (item, i) => (
            <div>
                <h3 className="course-title" id={`title-${idBase}-${i}`}>{item.display_name}</h3>
                <div className="course-metadata">
                    <span className="course-org metadata-item">
                        <span className="label">{gettext('Organization:')}</span>
                        <span className="value">{item.org}</span>
                    </span>
                    <span className="course-num metadata-item">
                        <span className="label">{gettext('Course Number:')}</span>
                        <span className="value">{item.number}</span>
                    </span>
                    {item.run
                        && (
                            <span className="course-run metadata-item">
                                <span className="label">{gettext('Course Run:')}</span>
                                <span className="value">{item.run}</span>
                            </span>
                        )}
                    {item.can_edit === false
                        && <span className="extra-metadata">{gettext('(Read-only)')}</span>}
                </div>
            </div>
        );

        return (
            <ul className="list-courses">
                {
                    props.items.map((item, i) => (
                        ((this.state.orgs.length === 0) || (this.state.orgs.indexOf(item.org) !== -1) || this.props.displayAll) && (
                            <li key={i} className="course-item" data-course-key={item.course_key}>
                                {item.url
                                    ? (
                                        <a className={linkClass} href={item.url}>
                                            {renderCourseMetadata(item, i)}
                                        </a>
                                    )
                                    : renderCourseMetadata(item, i)}
                                {item.lms_link && item.rerun_link
                                && (
                                    <ul className="item-actions course-actions">
                                        {allowReruns
                                            && (
                                                <li className="action action-rerun">
                                                    <a
                                                        href={item.rerun_link}
                                                        className="button rerun-button"
                                                        aria-labelledby={`re-run-${idBase}-${i} title-${idBase}-${i}`}
                                                        id={`re-run-${idBase}-${i}`}
                                                    >{gettext('Re-run Course')}
                                                    </a>
                                                </li>
                                            )}
                                        <li className="action action-view">
                                            <a
                                                href={item.lms_link}
                                                rel="external"
                                                className="button view-button"
                                                aria-labelledby={`view-live-${idBase}-${i} title-${idBase}-${i}`}
                                                id={`view-live-${idBase}-${i}`}
                                            >{gettext('View Live')}
                                            </a>
                                        </li>
                                    </ul>
                                )}
                            </li>
                        )
                    ))
                }
            </ul>
        );
    }
}

CourseOrLibraryListing.propTypes = {
    allowReruns: PropTypes.bool.isRequired,
    idBase: PropTypes.string.isRequired,
    items: PropTypes.arrayOf(PropTypes.object).isRequired,
    linkClass: PropTypes.string.isRequired,
};

export { CourseOrLibraryListing };
